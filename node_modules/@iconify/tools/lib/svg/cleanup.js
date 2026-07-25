import { removeBadAttributes } from "./cleanup/attribs.js";
import { checkBadTags } from "./cleanup/bad-tags.js";
import { cleanupInlineStyle } from "./cleanup/inline-style.js";
import { cleanupRootStyle } from "./cleanup/root-style.js";
import { cleanupSVGRoot } from "./cleanup/root-svg.js";
import { convertStyleToAttrs } from "./cleanup/svgo-style.js";

/**
* Clean up SVG before parsing/optimising it
*/
function cleanupSVG(svg, options) {
	cleanupInlineStyle(svg);
	convertStyleToAttrs(svg);
	cleanupSVGRoot(svg);
	checkBadTags(svg, options);
	removeBadAttributes(svg);
	cleanupRootStyle(svg);
}

export { cleanupSVG };