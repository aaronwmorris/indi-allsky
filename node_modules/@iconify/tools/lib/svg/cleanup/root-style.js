import { parseSVGStyle } from "../parse-style.js";

function assertNever(v) {}
/**
* Clean up root style
*
* This function removes all at-rule tokens, such as `@font-face`, `@media`
*/
function cleanupRootStyle(svg) {
	const result = {};
	parseSVGStyle(svg, (item) => {
		switch (item.type) {
			case "inline": return item.value;
			case "global": return item.value;
			case "at-rule":
				(result.removedAtRules || (result.removedAtRules = /* @__PURE__ */ new Set())).add(item.prop);
				return;
			case "keyframes":
				(result.animations || (result.animations = /* @__PURE__ */ new Set())).add(item.value);
				return item.value;
			default: assertNever(item);
		}
	});
	return result;
}

export { cleanupRootStyle };