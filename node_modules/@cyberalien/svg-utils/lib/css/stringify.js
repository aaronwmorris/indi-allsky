function indent(depth) {
	return "  ".repeat(depth);
}
/**
* Stringify CSS rules
*/
function stringifyCSSRules(rules, depth = 1) {
	const tab = indent(depth);
	const lines = [];
	for (const key in rules) {
		const value = rules[key];
		lines.push(`${tab}${key}: ${value};\n`);
	}
	return lines.join("");
}
/**
* Stringify CSS selector with rules
*/
function stringifyCSSSelector(selector, rules, depth = 0) {
	const content = typeof rules === "string" ? indent(depth + 1) + rules + "\n" : stringifyCSSRules(rules, depth + 1);
	if (!content.length) return "";
	const tab = indent(depth);
	return `${tab}${selector} {\n${content}${tab}}\n`;
}
/**
* Convert animation frames to CSS string
*
* Does not include @keyframes block, only the content
*/
function stringifyCSSAnimationFrames(keyframes, depth = 0) {
	const lines = [];
	const prop = keyframes.prop;
	const values = /* @__PURE__ */ new Map();
	keyframes.frames.forEach((frame) => {
		const css = `${indent(depth + 2)}${prop}: ${frame.value};\n`;
		const item = values.get(css);
		if (item) item.push(frame.time);
		else values.set(css, [frame.time]);
	});
	values.forEach((times, css) => {
		lines.push(`${indent(depth + 1)}${times.map((time) => `${(time * 100).toFixed(2).replace(/\.?0+$/, "")}%`).join(", ")} {\n${css}${indent(depth + 1)}}\n`);
	});
	return lines.join("").trim();
}
/**
* Stringify CSS keyframes
*/
function stringifyCSSKeyframes(animationName, keyframes, depth = 0) {
	const content = typeof keyframes === "string" ? keyframes : stringifyCSSAnimationFrames(keyframes, depth);
	if (content.includes("@keyframes")) return content;
	return `${indent(depth)}@keyframes ${animationName} {\n${indent(depth + 1)}${content}\n}\n`;
}
export { stringifyCSSAnimationFrames, stringifyCSSKeyframes, stringifyCSSRules, stringifyCSSSelector };
