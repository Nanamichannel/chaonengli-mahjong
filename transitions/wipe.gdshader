shader_type canvas_item;
//
// wipe.gdshader —— 用一张灰度遮罩把旧画面擦掉
// mask 值 1 = 已经揭开（露出下面的新场景），0 = 还盖着
//

uniform sampler2D mask_tex : filter_linear, repeat_disable;
uniform float softness = 0.06;
uniform float opacity = 1.0;

void fragment() {
	vec4 src = texture(TEXTURE, UV);
	float m = texture(mask_tex, UV).r;
	// 柔化：遮罩边缘做一点过渡，避免硬边
	float a = smoothstep(0.0, 1.0, clamp((m - 0.5) / max(softness, 0.001) + 0.5, 0.0, 1.0));
	a = mix(src.a, 0.0, a);
	COLOR = vec4(src.rgb, src.a * (1.0 - a) * opacity);
}
