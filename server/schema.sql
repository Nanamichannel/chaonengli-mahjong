-- ============================================================================
--  天才麻将少女 · 服务器数据库结构（SQLite）
--  ---------------------------------------------------------------------------
--  设计原则（很重要，别改错）：
--    1. 服务器权威：牌山顺序、别人的手牌，只存在这里，绝对不发给客户端。
--    2. 一张物理牌 = 一个唯一编号（wall_seq，0..135），所有表都用它指代具体牌。
--       （同一张"5m"有 4 张，用 wall_seq 才能分清是哪一张。）
--    3. 每做一个动作开一个事务，写到一半断电不会留下半个状态。
--    4. round_actions 记录每一个动作，配合 client_action_id 做幂等：
--       客户端断线重发同一个动作，服务器不会重复执行。
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ── 0. 元信息 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

-- ── 1. 账号 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname    TEXT    NOT NULL UNIQUE,
    pass_hash   TEXT,                          -- 游客账号可空
    is_guest    INTEGER NOT NULL DEFAULT 0,
    rating      INTEGER NOT NULL DEFAULT 1500, -- 天梯分（以后做匹配用）
    games       INTEGER NOT NULL DEFAULT 0,    -- 打过几局
    wins        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    last_login  TEXT
);

-- ── 2. 登录会话（断线重连靠这张表） ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT    PRIMARY KEY,           -- 随机串，客户端存着
    user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT,
    last_seen   TEXT
);

-- ── 3. 房间（开房 / 邀请码） ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rooms (
    room_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code   TEXT    NOT NULL UNIQUE,       -- 6 位邀请码
    host_user   INTEGER REFERENCES users(user_id),
    status      TEXT    NOT NULL DEFAULT 'waiting',  -- waiting/playing/finished/abandoned
    mode        TEXT    NOT NULL DEFAULT 'east_only',-- east_only(东风战) / hanchan(半庄)
    rule_json   TEXT    NOT NULL DEFAULT '{}', -- 规则开关：赤宝牌、食断、后付け、四家立直…
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT
);

-- ── 4. 房间座位（最多 4 个；真正的东南西北在对局开始时才定） ──────────────────
CREATE TABLE IF NOT EXISTS room_seats (
    room_id     INTEGER NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    seat        INTEGER NOT NULL,              -- 0..3 开房时的顺序
    user_id     INTEGER REFERENCES users(user_id),
    ready       INTEGER NOT NULL DEFAULT 0,
    joined_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (room_id, seat)
);

-- ── 5. 对局（一个房间打完一场 = 一条 match，包含很多个 round） ────────────────
CREATE TABLE IF NOT EXISTS matches (
    match_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     INTEGER REFERENCES rooms(room_id),
    status      TEXT    NOT NULL DEFAULT 'playing',  -- playing/finished/aborted
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at    TEXT,
    wall_seed   INTEGER,                       -- 洗牌种子（服务器专用，用于复盘）
    final_json  TEXT                           -- 终局分数 / 排位
);

CREATE TABLE IF NOT EXISTS match_seats (
    match_id    INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    seat        INTEGER NOT NULL,              -- 0=东 1=南 2=西 3=北（整场固定）
    user_id     INTEGER REFERENCES users(user_id),
    nickname    TEXT,                          -- 冗余一份，查询方便
    score       INTEGER NOT NULL DEFAULT 25000,
    is_ai       INTEGER NOT NULL DEFAULT 0,
    connected   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (match_id, seat)
);

-- ── 6. 每一局（东1局0本场 这种） ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rounds (
    round_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id     INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    round_index  INTEGER NOT NULL,             -- 本场对局里的第几局，从 1 开始
    wind         TEXT    NOT NULL,             -- 场风 dong/nan
    number       INTEGER NOT NULL,             -- 局数 1..4
    honba        INTEGER NOT NULL DEFAULT 0,   -- 本场
    dealer_seat  INTEGER NOT NULL,             -- 亲家 0..3
    riichi_sticks INTEGER NOT NULL DEFAULT 0,  -- 场上立直棒（供托）
    kan_count    INTEGER NOT NULL DEFAULT 0,   -- 本局杠的次数（决定岭上牌）
    status       TEXT    NOT NULL DEFAULT 'playing', -- playing/ended
    turn_seat    INTEGER,                      -- 现在轮到谁（服务器自动托管用）
    turn_deadline TEXT,                        -- 出牌截止时间（超时自动摸切）
    live_left    INTEGER NOT NULL DEFAULT 0,   -- 牌山还剩几张可摸
    started_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at     TEXT,
    result       TEXT,                         -- tsumo/ron/ryuukyoku(荒牌流局)/kyuushu(九种九牌)
                                               -- sufon_renda/sucha_riichi/sukan_santan/sanchahou/chombo
    winner_seat  INTEGER,
    loser_seat   INTEGER,                      -- 放铳的人
    han          INTEGER,
    fu           INTEGER,
    points       INTEGER,
    yaku_json    TEXT,                         -- 役种明细
    dora_json    TEXT,                         -- 宝牌/里宝牌明细
    UNIQUE (match_id, round_index)
);

-- ── 7. 牌山（【服务器专用】绝不发给客户端） ─────────────────────────────────
--    seq = 洗牌后的物理位置 0..135
--    zone: live(可摸的牌山) / dead(王牌) / dora_ind(宝牌指示牌) / ura_dora(里宝牌指示牌)
--    draw_no: 如果是 live，第几次被摸到（0 起；杠了会从 dead 补岭上牌）
CREATE TABLE IF NOT EXISTS round_wall (
    round_id    INTEGER NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    tile        TEXT    NOT NULL,              -- '1m'..'9m','0m'(赤5),'1p','1s','dong'..'zhong'
    zone        TEXT    NOT NULL DEFAULT 'live',
    draw_no     INTEGER,
    dealt_to    INTEGER,                       -- 发牌发给了谁（NULL = 还在牌山）
    PRIMARY KEY (round_id, seq)
);

-- ── 8. 手牌（【服务器专用】自己那份才发给本人） ─────────────────────────────
CREATE TABLE IF NOT EXISTS round_hands (
    round_id    INTEGER NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    seat        INTEGER NOT NULL,
    wall_seq    INTEGER NOT NULL,              -- 对应 round_wall.seq
    tile        TEXT    NOT NULL,
    slot        INTEGER NOT NULL DEFAULT 0,    -- 服务器给的排位（理牌后）
    is_drawn    INTEGER NOT NULL DEFAULT 0,    -- 1 = 刚摸进还没打出的那张
    PRIMARY KEY (round_id, wall_seq)
);

-- ── 9. 牌河 ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS round_discards (
    round_id    INTEGER NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,              -- 全场第几张打出的，从 1 开始
    seat        INTEGER NOT NULL,
    wall_seq    INTEGER NOT NULL,
    tile        TEXT    NOT NULL,
    is_tsumogiri INTEGER NOT NULL DEFAULT 0,   -- 摸切
    is_riichi_tile INTEGER NOT NULL DEFAULT 0, -- 立直宣言牌（横置）
    face_down   INTEGER NOT NULL DEFAULT 0,    -- 1 = 暗牌（换牌技能放进牌河的）
    is_nuki     INTEGER NOT NULL DEFAULT 0,    -- 1 = 拔北放下的北（不算振听）
    called      INTEGER NOT NULL DEFAULT 0,    -- 被吃/碰/杠拿走了
    called_by   INTEGER,
    called_kind TEXT,                          -- chi/pon/kan
    PRIMARY KEY (round_id, seq)
);

-- ── 10. 副露 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS round_melds (
    round_id    INTEGER NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    meld_id     INTEGER NOT NULL,              -- 该家的第几组副露（0 起）
    seat        INTEGER NOT NULL,
    kind        TEXT    NOT NULL,              -- chi/pon/minkan/ankan/kakan
    called_tile TEXT    NOT NULL,              -- 鸣的那张
    from_seat   INTEGER NOT NULL,              -- 谁打出的（暗杠 = 自己）
    tiles_json  TEXT    NOT NULL,              -- 三/四张的显示顺序
    rot_index   INTEGER NOT NULL DEFAULT 0,    -- 横置那张在 tiles_json 里的下标（-1 = 无）
    from_discard_seq INTEGER,                  -- 对应 round_discards.seq
    seqs_json   TEXT    NOT NULL DEFAULT '[]', -- 与 tiles_json 一一对应：每组牌是「哪几张物理牌」
                                               --（wall_seq，和 round_wall.seq 对应；加杠就是 4 个）
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (round_id, seat, meld_id)
);

-- ── 11. 立直状态 ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS round_riichi (
    round_id    INTEGER NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    seat        INTEGER NOT NULL,
    declared_seq INTEGER,                      -- 宣言时对应的 round_actions.seq
    ippatsu     INTEGER NOT NULL DEFAULT 1,    -- 一发还有效吗
    PRIMARY KEY (round_id, seat)
);

-- ── 12. 宝牌（指示牌 → 实际宝牌） ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS round_dora (
    round_id    INTEGER NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL,              -- dora / ura
    idx         INTEGER NOT NULL,
    indicator   TEXT    NOT NULL,
    dora        TEXT    NOT NULL,
    revealed    INTEGER NOT NULL DEFAULT 0,    -- 是否已翻开（杠了才追加翻开）
    PRIMARY KEY (round_id, kind, idx)
);

-- ── 13. 动作日志（服务器权威：重连、回放、防作弊、审计） ────────────────────
CREATE TABLE IF NOT EXISTS round_actions (
    round_id    INTEGER NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,              -- 本局第几个动作，从 1 开始
    seat        INTEGER,                       -- -1 = 系统/服务器
    action      TEXT    NOT NULL,              -- round_start/draw/discard/chi/pon/kan/riichi/tsumo/ron/pass/ryuukyoku/round_end
    payload     TEXT    NOT NULL DEFAULT '{}',
    client_action_id TEXT,                     -- 客户端带的动作号（幂等去重）
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (round_id, seq),
    UNIQUE (round_id, seat, client_action_id)
);

-- ── 14. 分数流水 ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS score_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id    INTEGER REFERENCES rounds(round_id) ON DELETE CASCADE,
    seat        INTEGER,
    delta       INTEGER NOT NULL,
    after       INTEGER,
    reason      TEXT    NOT NULL,              -- tsumo/ron/riichi/noten/honba/kyuushu…
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── 15. 本局的临时状态（同巡振听 / 立直后见逃 / 一发 / 双立直…）──────────────
--  服务器按「一次请求 = 一个进程」跑，这些只在内存里的东西必须落库，否则换个进程来问就丢了。
CREATE TABLE IF NOT EXISTS round_flags (
    round_id    INTEGER PRIMARY KEY REFERENCES rounds(round_id) ON DELETE CASCADE,
    flags_json  TEXT    NOT NULL DEFAULT '{}',
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================================
--  视图：给客户端看的「公开信息」都从视图取，避免手滑把私密数据发出去
-- ============================================================================

-- 房间大厅
CREATE VIEW IF NOT EXISTS v_room_summary AS
SELECT r.room_id, r.room_code, r.status, r.mode,
       (SELECT COUNT(*) FROM room_seats s WHERE s.room_id = r.room_id) AS players,
       (SELECT nickname FROM users u WHERE u.user_id = r.host_user)     AS host
FROM rooms r;

-- 分数面板
CREATE VIEW IF NOT EXISTS v_match_score AS
SELECT ms.match_id, ms.seat, ms.nickname, ms.score, ms.connected,
       CASE ms.seat WHEN 0 THEN '东' WHEN 1 THEN '南' WHEN 2 THEN '西' ELSE '北' END AS wind
FROM match_seats ms;

-- 本局公开状态（不含任何人的手牌、不含牌山）
CREATE VIEW IF NOT EXISTS v_public_round AS
SELECT r.round_id, r.match_id, r.wind, r.number, r.honba, r.dealer_seat,
       r.turn_seat, r.turn_deadline, r.live_left, r.riichi_sticks, r.kan_count,
       r.status, r.result, r.winner_seat, r.loser_seat, r.han, r.fu, r.points
FROM rounds r;

-- 公开的牌河
CREATE VIEW IF NOT EXISTS v_public_discards AS
SELECT round_id, seq, seat, tile, is_tsumogiri, is_riichi_tile, called, called_by, called_kind
FROM round_discards;

-- 公开的副露
CREATE VIEW IF NOT EXISTS v_public_melds AS
SELECT round_id, seat, meld_id, kind, called_tile, from_seat, tiles_json, rot_index
FROM round_melds;

-- 公开的宝牌（只给已经翻开的）
CREATE VIEW IF NOT EXISTS v_public_dora AS
SELECT round_id, kind, idx, indicator, dora FROM round_dora WHERE revealed = 1;

-- 各家手牌「张数」——公开信息，但不暴露是什么牌
CREATE VIEW IF NOT EXISTS v_hand_counts AS
SELECT round_id, seat, COUNT(*) AS tiles, SUM(is_drawn) AS drawn
FROM round_hands GROUP BY round_id, seat;

-- ============================================================================
--  索引
-- ============================================================================
CREATE INDEX IF NOT EXISTS ix_hands_seat     ON round_hands(round_id, seat);
CREATE INDEX IF NOT EXISTS ix_discards_seat  ON round_discards(round_id, seat, seq);
CREATE INDEX IF NOT EXISTS ix_actions_seat   ON round_actions(round_id, seat, seq);
CREATE INDEX IF NOT EXISTS ix_wall_draw      ON round_wall(round_id, zone, draw_no);
CREATE INDEX IF NOT EXISTS ix_room_seats     ON room_seats(user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user  ON sessions(user_id);
