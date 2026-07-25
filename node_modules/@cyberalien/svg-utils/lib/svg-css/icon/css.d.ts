import { CSSGeneratedStylesheet } from "../../css/types.js";
import { SVGCSSIconRules, SVGCSSStatefulIconRules } from "./types.js";
import { StatefulIconSelectorsContext } from "../states/selector/types.js";
type StylesheetParam = CSSGeneratedStylesheet | ((selector: string) => CSSGeneratedStylesheet);
/**
 * Add styles for stateful icon to stylesheet
 *
 * If commonStylesheet is an object, all styles will be added to it and result
 * will contain the same stylesheet for all classes.
 *
 * If commonStylesheet is not an object, styles will be separated into different
 * stylesheets for classes and keyframes, which can be reused across icons.
 */
declare function renderStatefulSVGCSSIconStyle(icon: SVGCSSStatefulIconRules, context: StatefulIconSelectorsContext | null, commonStylesheet?: StylesheetParam): Record<string, CSSGeneratedStylesheet>;
/**
 * Add styles for icon to stylesheet
 *
 * If commonStylesheet is an object, all styles will be added to it and result
 * will contain the same stylesheet for all classes.
 *
 * If commonStylesheet is not an object, styles will be separated into different
 * stylesheets for classes and keyframes, which can be reused across icons.
 */
declare function renderSVGCSSIconStyle(icon: SVGCSSIconRules, commonStylesheet?: StylesheetParam): Record<string, CSSGeneratedStylesheet>;
export { renderSVGCSSIconStyle, renderStatefulSVGCSSIconStyle };