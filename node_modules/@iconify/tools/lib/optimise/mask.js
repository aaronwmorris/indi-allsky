import { isEmptyColor, parseColors } from "../colors/parse.js";
import { iconToHTML, parseSVGContent, splitSVGDefs } from "@iconify/utils";

const defaultBlackColors = [
	"black",
	"#000",
	"#000000"
];
const defaultWhiteColors = [
	"white",
	"#fff",
	"#ffffff"
];
const defaultOptions = {
	color: "currentColor",
	solid: [...defaultBlackColors, "currentcolor"],
	transparent: defaultWhiteColors,
	force: false,
	id: "mask"
};
/**
* Converts SVG to mask
*
* Fixes badly designed icons, which use white shape where icon supposed to be transparent
*/
function convertSVGToMask(svg, options = {}) {
	const props = {
		...defaultOptions,
		...options
	};
	const check = (test, value, color) => {
		if (typeof test === "string") return value.toLowerCase() === test;
		if (test instanceof Array) return test.includes(value.toLowerCase());
		return test(value, color);
	};
	let foundSolid = false;
	let foundTransparent = false;
	let failed = false;
	let hasCustomValue = false;
	const backup = svg.toString();
	parseColors(svg, { callback: (attr, colorStr, color) => {
		if (!color || isEmptyColor(color)) return colorStr;
		if (props.custom) {
			let customValue = props.custom(colorStr.toLowerCase(), color);
			if (typeof customValue === "number") {
				let str = Math.max(Math.min(Math.round(customValue * 255), 255), 0).toString(16);
				if (str.length < 2) str = "0" + str;
				if (str[0] === str[1]) str = str[0];
				customValue = "#" + str + str + str;
			}
			if (typeof customValue === "string") {
				if (defaultBlackColors.includes(customValue)) foundSolid = true;
				else if (defaultWhiteColors.includes(customValue)) foundTransparent = true;
				else hasCustomValue = true;
				return customValue;
			}
		}
		if (check(props.solid, colorStr, color)) {
			foundSolid = true;
			return "#fff";
		}
		if (check(props.transparent, colorStr, color)) {
			foundTransparent = true;
			return "#000";
		}
		failed = true;
		console.warn("Unexpected color:", colorStr);
		return color;
	} });
	if (failed || !(hasCustomValue || foundSolid && foundTransparent) && !props.force) {
		svg.load(backup);
		return false;
	}
	const parsed = parseSVGContent(svg.toString());
	if (!parsed) return false;
	const { defs, content } = splitSVGDefs(parsed.body);
	const viewBox = svg.viewBox;
	const newContent = iconToHTML(`<defs>${defs}<mask id="${props.id}">${content}</mask></defs><rect mask="url(#${props.id})" ${viewBox.left ? `x="${viewBox.left}" ` : ""}${viewBox.top ? `y="${viewBox.top}" ` : ""}width="${viewBox.width}" height="${viewBox.height}" fill="${props.color}" />`, parsed.attribs);
	svg.load(newContent);
	return true;
}

export { convertSVGToMask };