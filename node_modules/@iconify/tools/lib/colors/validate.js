import { parseColors } from "./parse.js";
import { colorToString } from "@iconify/utils/lib/colors";

/**
* Validate colors in icon
*
* If icon is monotone,
*
* Throws exception on error
*/
function validateColors(svg, expectMonotone, options) {
	const palette = parseColors(svg, options);
	palette.colors.forEach((color) => {
		if (typeof color === "string") throw new Error("Unexpected color: " + color);
		switch (color.type) {
			case "none":
			case "transparent": return;
			case "current":
				if (!expectMonotone) throw new Error("Unexpected color: " + colorToString(color));
				return;
			case "rgb":
			case "hsl":
				if (expectMonotone) throw new Error("Unexpected color: " + colorToString(color));
				return;
			default: if (color.type !== "function" || color.func !== "url") throw new Error("Unexpected color: " + colorToString(color));
		}
	});
	return palette;
}

export { validateColors };