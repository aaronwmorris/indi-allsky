import { CSSRules } from "../../css/types.js";
/**
 * Callback type for generating CSS variable name based on value
 */
type ConvertSVGPropertyVariableCallback = (lowerCaseValue: string) => string | undefined;
/**
 * Options for converting SVG properties to CSS
 */
interface ConvertSVGPropertyToCSSOptions {
  legacy?: boolean;
  vars?: Record<string, ConvertSVGPropertyVariableCallback>;
}
/**
 * Result of converting SVG properties to CSS
 */
interface SVGConvertedToCSSProperties {
  props: string[];
  rules: CSSRules;
}
export { ConvertSVGPropertyToCSSOptions, ConvertSVGPropertyVariableCallback, SVGConvertedToCSSProperties };