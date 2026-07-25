/**
 * SVG property types
 */
declare const propTypes: readonly ["path", "px", "raw"];
type SVGPropertyType = (typeof propTypes)[number];
/**
 * Get property type
 */
declare function getSVGPropertyType(tag: string, prop: string, supportLegacyBrowsers?: boolean): SVGPropertyType | undefined;
export { getSVGPropertyType };