import { SVG } from "./index.js";
import { CheckBadTagsOptions } from "./cleanup/bad-tags.js";
/**
 * Options
 */
type CleanupSVGOptions = CheckBadTagsOptions;
/**
 * Clean up SVG before parsing/optimising it
 */
declare function cleanupSVG(svg: SVG, options?: CleanupSVGOptions): void;
export { CleanupSVGOptions, cleanupSVG };