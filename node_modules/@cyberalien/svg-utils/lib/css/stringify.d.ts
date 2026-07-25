import { CSSKeyframes, CSSRules } from "./types.js";
/**
 * Stringify CSS rules
 */
declare function stringifyCSSRules(rules: CSSRules, depth?: number): string;
/**
 * Stringify CSS selector with rules
 */
declare function stringifyCSSSelector(selector: string, rules: string | CSSRules, depth?: number): string;
/**
 * Convert animation frames to CSS string
 *
 * Does not include @keyframes block, only the content
 */
declare function stringifyCSSAnimationFrames(keyframes: CSSKeyframes, depth?: number): string;
/**
 * Stringify CSS keyframes
 */
declare function stringifyCSSKeyframes(animationName: string, keyframes: CSSKeyframes | string, depth?: number): string;
export { stringifyCSSAnimationFrames, stringifyCSSKeyframes, stringifyCSSRules, stringifyCSSSelector };