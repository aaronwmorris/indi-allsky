function cleanupValue(value) {
	return value.replace(/[^a-z0-9]/g, "-").replace(/-+/g, "-").replace(value.startsWith("-") ? /-+$/g : /^-+|-+$/g, "");
}
const colorVar = (color) => color === "currentcolor" ? void 0 : `--svg-color--${cleanupValue(color)}`;
/**
* Default CSS variable callbacks for SVG properties
*/
const defaultSVGCSSPropertyVars = {
	"stroke": colorVar,
	"fill": colorVar,
	"stop-color": colorVar,
	"stroke-width": (value) => `--svg-stroke-width--${cleanupValue(value)}`,
	"opacity": (value) => `--svg-opacity--${cleanupValue(value)}`,
	"fill-opacity": (value) => `--svg-fill-opacity--${cleanupValue(value)}`
};
export { defaultSVGCSSPropertyVars };
