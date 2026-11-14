shader_type canvas_item;
//
// mask_poly.gdshader —— 用多边形做蒙版（AE 蒙版路径）
// points 是 AE 图层坐标系里的原始点（原点 = 图层左上角，单位 = 像素）。
// 这里用 UV × 图层尺寸换算回同一坐标系，不依赖 VERTEX（纯色层是 1×1 贴图放大，空间不一致）。
//

uniform int count = 0;
uniform vec2 points[512];
uniform vec2 layer_size = vec2(1.0, 1.0);
uniform vec2 layer_anchor = vec2(0.0, 0.0);

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
	if (count >= 3) {
		vec2 imgpos = UV * layer_size;
		if (!inside_polygon(imgpos)) {
			discard;
		}
	}
	COLOR = texture(TEXTURE, UV) * COLOR;
}
