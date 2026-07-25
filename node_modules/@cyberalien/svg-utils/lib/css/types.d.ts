import { UniqueHashPartialOptions } from "../helpers/hash/types.js";
/**
 * CSS rules
 */
type CSSRules = Record<string, string>;
/**
 * Animation keyframes
 */
interface CSSKeyframe {
  time: number;
  value: string;
}
interface CSSKeyframes {
  prop: string;
  frames: CSSKeyframe[];
}
/**
 * Hash options
 */
type CSSHashOptions = UniqueHashPartialOptions;
/**
 * Generated stylesheet
 */
interface CSSGeneratedSelector {
  rules?: CSSRules | string;
  nested?: CSSGeneratedSelectors;
}
type CSSGeneratedSelectors = Record<string, CSSGeneratedSelector>;
interface CSSGeneratedStylesheet {
  selectors: CSSGeneratedSelectors;
  keyframes: Record<string, CSSKeyframes | string>;
}
export { CSSGeneratedSelector, CSSGeneratedSelectors, CSSGeneratedStylesheet, CSSHashOptions, CSSKeyframe, CSSKeyframes, CSSRules };