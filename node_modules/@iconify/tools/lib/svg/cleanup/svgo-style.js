import { parseSVGStyle } from "../parse-style.js";
import { badAttributePrefixes, badAttributes, badSoftwareAttributes } from "../data/attributes.js";
import { runSVGO } from "../../optimise/svgo.js";

/**
* Expand inline style
*/
function convertStyleToAttrs(svg) {
	let hasStyle = false;
	parseSVGStyle(svg, (item) => {
		if (item.type !== "inline" && item.type !== "global") return item.value;
		const prop = item.prop;
		if (badAttributes.has(prop) || badSoftwareAttributes.has(prop) || badAttributePrefixes.has(prop.split("-").shift())) return;
		hasStyle = true;
		return item.value;
	});
	if (!hasStyle) return;
	runSVGO(svg, {
		plugins: ["convertStyleToAttrs", "inlineStyles"],
		multipass: true
	});
}

export { convertStyleToAttrs };