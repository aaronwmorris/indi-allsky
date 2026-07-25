import { isEmptyColor, parseColors } from "./parse.js";

/**
* Detect palette
*
* Returns null if icon set has mixed colors
*/
function detectIconSetPalette(iconSet) {
	let palette;
	iconSet.forEachSync((name) => {
		if (palette === null) return;
		const svg = iconSet.toSVG(name);
		if (!svg) return;
		let iconPalette;
		parseColors(svg, { callback: (attr, colorStr, color) => {
			if (!color) {
				iconPalette = null;
				return colorStr;
			}
			if (iconPalette === null || isEmptyColor(color)) return color;
			const isColor = color.type !== "current";
			if (iconPalette === void 0) {
				iconPalette = isColor;
				return color;
			}
			if (iconPalette !== isColor) iconPalette = null;
			return color;
		} });
		if (iconPalette === void 0) iconPalette = null;
		if (palette === void 0) palette = iconPalette;
		else if (palette !== iconPalette) palette = null;
	}, ["icon"]);
	return palette ?? null;
}

export { detectIconSetPalette };