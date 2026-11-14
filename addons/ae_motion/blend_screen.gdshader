shader_type canvas_item;
//
// blend_screen.gdshader —— AE 的"需要与底图运算"的混合模式
// 用法：给图层挂这个材质，mode 填下面常量之一；
//       并在该图层之前放一个 BackBufferCopy（COPY_MODE_VIEWPORT）。
//
// 公式里 a = 底图（已经画好的画面），b = 本层。
//

uniform sampler2D screen_tex : hint_screen_texture, repeat_disable, filter_nearest;
uniform int mode = 0;

const int SCREEN = 1;
const int OVERLAY = 2;
const int SOFT_LIGHT = 3;
const int HARD_LIGHT = 4;
const int COLOR_DODGE = 5;
const int COLOR_BURN = 6;
const int DIFFERENCE = 7;
const int EXCLUSION = 8;
const int DARKEN = 9;
const int LIGHTEN = 10;
const int VIVID_LIGHT = 11;
const int LINEAR_LIGHT = 12;
const int PIN_LIGHT = 13;
const int HARD_MIX = 14;
const int DIVIDE = 15;
const int LINEAR_BURN = 16;

float blend_ch(float a, float b, int m) {
	if (m == SCREEN) {
		return 1.0 - (1.0 - a) * (1.0 - b);
	} else if (m == OVERLAY) {
		return a < 0.5 ? 2.0 * a * b : 1.0 - 2.0 * (1.0 - a) * (1.0 - b);
	} else if (m == SOFT_LIGHT) {
		if (b <= 0.5) {
			return a - (1.0 - 2.0 * b) * a * (1.0 - a);
		}
		float d = (a <= 0.25) ? ((16.0 * a - 12.0) * a + 4.0) * a : sqrt(a);
		return a + (2.0 * b - 1.0) * (d - a);
	} else if (m == HARD_LIGHT) {
		return b < 0.5 ? 2.0 * a * b : 1.0 - 2.0 * (1.0 - a) * (1.0 - b);
	} else if (m == COLOR_DODGE) {
		if (a <= 0.0) return 0.0;
		if (b >= 1.0) return 1.0;
		return min(1.0, a / (1.0 - b));
	} else if (m == COLOR_BURN) {
		if (a >= 1.0) return 1.0;
		if (b <= 0.0) return 0.0;
		return 1.0 - min(1.0, (1.0 - a) / b);
	} else if (m == DIFFERENCE) {
		return abs(a - b);
	} else if (m == EXCLUSION) {
		return a + b - 2.0 * a * b;
	} else if (m == DARKEN) {
		return min(a, b);
	} else if (m == LIGHTEN) {
		return max(a, b);
	} else if (m == VIVID_LIGHT) {
		if (b <= 0.5) {
			return b <= 0.0 ? 0.0 : max(0.0, 1.0 - (1.0 - a) / (2.0 * b));
		}
		return b >= 1.0 ? 1.0 : min(1.0, a / (2.0 * (1.0 - b)));
	} else if (m == LINEAR_LIGHT) {
		return clamp(a + 2.0 * b - 1.0, 0.0, 1.0);
	} else if (m == PIN_LIGHT) {
		if (b < 0.5) return min(a, 2.0 * b);
		return max(a, 2.0 * b - 1.0);
	} else if (m == HARD_MIX) {
		return (a + b >= 1.0) ? 1.0 : 0.0;
	} else if (m == DIVIDE) {
		return b <= 0.0 ? 1.0 : min(1.0, a / b);
	} else if (m == LINEAR_BURN) {
		return clamp(a + b - 1.0, 0.0, 1.0);
	}
	return b;
}

void fragment() {
	vec4 src = texture(TEXTURE, UV) * COLOR;
	vec3 back = texture(screen_tex, SCREEN_UV).rgb;
	vec3 blended = vec3(
		blend_ch(back.r, src.rgb.r, mode),
		blend_ch(back.g, src.rgb.g, mode),
		blend_ch(back.b, src.rgb.b, mode));

	// 本层透明的地方原样保留底图，这样不会把画面擦掉
	vec3 outc = mix(back, blended, src.a);
	COLOR = vec4(outc, 1.0);
}
