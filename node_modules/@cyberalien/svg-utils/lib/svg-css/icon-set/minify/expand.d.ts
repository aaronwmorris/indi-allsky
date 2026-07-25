import { SVGCSSIconSet, SVGCSSIconSetClassData } from "../types.js";
/**
 * Expand class content from icon set
 */
declare function expandSVGCSSIconSetClass(css: Required<SVGCSSIconSet>['css'], classContent: SVGCSSIconSetClassData): void;
/**
 * Expand fallback prefix
 */
declare function expandSVGCSSIconSetFallback(iconSet: SVGCSSIconSet): void;
/**
 * Unminify icon set
 */
declare function expandSVGCSSIconSet(iconSet: SVGCSSIconSet): void;
export { expandSVGCSSIconSet, expandSVGCSSIconSetClass, expandSVGCSSIconSetFallback };