import { SVG } from "../index.js";
/**
 * Options
 */
interface CheckBadTagsOptions {
  keepTitles?: boolean;
}
/**
 * Test for bag tags
 */
declare function checkBadTags(svg: SVG, options?: CheckBadTagsOptions): void;
export { CheckBadTagsOptions, checkBadTags };