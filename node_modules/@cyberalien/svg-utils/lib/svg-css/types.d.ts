import { CSSHashOptions, CSSKeyframes, CSSRules } from "../css/types.js";
import { StringifyXMLOptions } from "../xml/types.js";
import { ConvertSVGPropertyToCSSOptions } from "./props/types.js";
/**
 * Options for converting SVG tags to SVG+CSS
 */
interface BaseConvertSVGContentOptions extends CSSHashOptions, ConvertSVGPropertyToCSSOptions {}
/**
 * Options for converting SVG content to SVG+CSS
 */
interface ConvertSVGContentOptions extends StringifyXMLOptions, BaseConvertSVGContentOptions {}
/**
 * Result of converting SVG content to SVG+CSS
 */
interface ConvertedSVGContent {
  content: string;
  classes?: Record<string, CSSRules>;
  keyframes?: Record<string, CSSKeyframes>;
}
export { BaseConvertSVGContentOptions, ConvertSVGContentOptions, ConvertedSVGContent };