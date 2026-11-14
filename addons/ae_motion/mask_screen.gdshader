shader_type canvas_item;
//
// mask_screen.gdshader —— 把多边形蒙版应用到任意 2D 图层（通常是"上一屏"）
// 点在多边形外就丢弃像素。适合做角色遮挡式的转场。
//
// points 用 AE 图层坐标（原点=图层左上角，单位=像素），
// 通过 layer_size / layer_anchor 换算，所以和贴图实际尺寸无关。
//

uniform int count = 0;
uniform vec2 points[512];
uniform vec2 comp_size = vec2(1920.0, 1080.0);
uniform float feather = 0.0;

bool inside_polygon(vec2 p) {
	bool inside = false;
	int n = count;
	for (int i = 0; i < 512; i++) {
		if (i >= n) break;
		int j = i + 1;
		if (j >= n) j = 0;
		vec2 a = points[i];
		vec2 b = points[j];
		if (((a.y > p.y) != (b.y > p.y)) &&
			(p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x)) {
			inside = !inside;
		}
	}
	return inside;
}

void fragment() {
	vec2 imgpos = UV * comp_size;
	if (count >= 3 && !inside_polygon(imgpos)) {
		discard;
	}
	COLOR = texture(TEXTURE, UV) * COLOR;
}
