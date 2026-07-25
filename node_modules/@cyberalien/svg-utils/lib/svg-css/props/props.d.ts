import { ParsedXMLTagElement } from "../../xml/types.js";
import { ConvertSVGPropertyToCSSOptions, SVGConvertedToCSSProperties } from "./types.js";
/**
 * Extract SVG tag properties that can be converted to CSS
 *
 * Returns CSS rules, does not add a class to tag, but does remove properties from tag
 */
declare function extractSVGTagPropertiesForCSS(tag: ParsedXMLTagElement, options?: ConvertSVGPropertyToCSSOptions): SVGConvertedToCSSProperties | undefined;
export { extractSVGTagPropertiesForCSS };