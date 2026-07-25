/**
* SVG property types
*/
const propTypes = [
	"path",
	"px",
	"raw"
];
/**
* Props shared between multiple shapes
*/
const commonShapes = { px: [
	"width",
	"height",
	"x",
	"y",
	"cx",
	"cy",
	"r",
	"rx",
	"ry"
] };
/**
* Shape specific properties that can be converted to CSS
*/
const props = {
	"*": {
		px: ["stroke-width"],
		raw: [
			"fill",
			"stroke",
			"color",
			"opacity"
		]
	},
	"path": { path: ["d"] },
	"ellipse": commonShapes,
	"circle": commonShapes,
	"rect": commonShapes,
	"stop": { raw: ["stop-color", "stop-opacity"] }
};
const skipTags = [
	"animate",
	"animateMotion",
	"animateTransform",
	"set",
	"discard"
];
const legacyProps = ["d"];
/**
* Get property type
*/
function getSVGPropertyType(tag, prop, supportLegacyBrowsers = false) {
	if (skipTags.includes(tag)) return;
	if (supportLegacyBrowsers && legacyProps.includes(prop)) return;
	for (const type of propTypes) if (props[tag]?.[type]?.includes(prop) || props["*"]?.[type]?.includes(prop)) return type;
	if (prop.startsWith("stroke") || prop.startsWith("fill")) return "raw";
}
export { getSVGPropertyType };
