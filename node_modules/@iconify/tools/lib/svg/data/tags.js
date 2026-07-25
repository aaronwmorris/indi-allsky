/**
* This list is highly opinionated. It is designed to handle icons that can be safely embedded in HTML and linked as external source.
* Icons cannot have anything that requires external resources, anything that renders inconsistently.
*/
/**
* Bad tags
*
* Parser should throw error if one of these tags is found
*
* List includes text tags because:
* - it usuaully uses custom font, which makes things much more complex
* - it renders differently on different operating systems and browsers
*
* View tag is not allowed because it requires targeting view by id from external source, making it unusable in embedded icons.
*/
const badTags = new Set([
	"foreignObject",
	"script",
	"image",
	"feImage",
	"animateColor",
	"altGlyph",
	"text",
	"tspan",
	"switch",
	"textPath",
	"font",
	"font-face",
	"glyph",
	"missing-glyph",
	"hkern",
	"vhern",
	"view",
	"a"
]);
/**
* Deprecated or irrelevant tags
*
* Tags that are quietly removed
*/
const unsupportedTags = new Set([
	"metadata",
	"desc",
	"title"
]);
/**
* Style
*/
const styleTag = new Set(["style"]);
/**
* Definitions: reusable elements inside
*/
const defsTag = new Set(["defs"]);
/**
* Masks: colors are ignored, elements must have id
*/
const maskTags = new Set(["clipPath", "mask"]);
/**
* Symbol
*/
const symbolTag = new Set(["symbol"]);
/**
* SVG shapes
*/
const shapeTags = new Set([
	"circle",
	"ellipse",
	"line",
	"path",
	"polygon",
	"polyline",
	"rect"
]);
/**
* Use
*/
const useTag = new Set(["use"]);
/**
* Groups
*/
const groupTag = new Set(["g"]);
/**
* Marker, should be inside <defs>
*/
const markerTag = new Set(["marker"]);
/**
* SVG animations
*/
const animateTags = new Set([
	"animate",
	"animateMotion",
	"animateTransform",
	"discard",
	"set"
]);
const animateMotionChildTags = new Set(["mpath"]);
/**
* Gradients, should be inside <defs>
*/
const gradientTags = new Set(["linearGradient", "radialGradient"]);
/**
* Gradient color, must be inside one of gradientTags
*/
const gradientChildTags = new Set(["stop"]);
/**
* Pattern, should be inside <defs>
*/
const patternTag = new Set(["pattern"]);
/**
* Filters
*/
const filterTag = new Set(["filter"]);
const feLightningTags = new Set(["feDiffuseLighting", "feSpecularLighting"]);
const filterChildTags = new Set([
	"feBlend",
	"feColorMatrix",
	"feComponentTransfer",
	"feComposite",
	"feConvolveMatrix",
	"feDisplacementMap",
	"feDropShadow",
	"feFlood",
	"feGaussianBlur",
	"feMerge",
	"feMorphology",
	"feOffset",
	"feTile",
	"feTurbulence",
	...feLightningTags
]);
const feComponentTransferChildTag = new Set([
	"feFuncR",
	"feFuncG",
	"feFuncB",
	"feFuncA"
]);
const feLightningChildTags = new Set([
	"feSpotLight",
	"fePointLight",
	"feDistantLight"
]);
const feMergeChildTags = new Set(["feMergeNode"]);
/***** Combination of tags *****/
/**
* Reusable elements that use colors
*
* Most are used via color attributes like `fill`
* Some are used via custom attributes like `marker-start`
* Filter is used via `filter`
*/
const reusableElementsWithPalette = new Set([
	...gradientTags,
	...patternTag,
	...markerTag,
	...symbolTag,
	...filterTag
]);
/**
* All supported tags
*/
const allValidTags = new Set([
	...styleTag,
	...defsTag,
	...maskTags,
	...symbolTag,
	...shapeTags,
	...useTag,
	...groupTag,
	...markerTag,
	...animateTags,
	...animateMotionChildTags,
	...gradientTags,
	...gradientChildTags,
	...patternTag,
	...filterTag,
	...filterChildTags,
	...feComponentTransferChildTag,
	...feLightningChildTags,
	...feMergeChildTags
]);

export { allValidTags, animateMotionChildTags, animateTags, badTags, defsTag, feComponentTransferChildTag, feLightningChildTags, feLightningTags, feMergeChildTags, filterChildTags, filterTag, gradientChildTags, gradientTags, groupTag, markerTag, maskTags, patternTag, reusableElementsWithPalette, shapeTags, styleTag, symbolTag, unsupportedTags, useTag };