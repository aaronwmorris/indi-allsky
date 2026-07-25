import { SVG } from "../index.js";
interface CleanupRootStyleResult {
  animations?: Set<string>;
  removedAtRules?: Set<string>;
}
/**
 * Clean up root style
 *
 * This function removes all at-rule tokens, such as `@font-face`, `@media`
 */
declare function cleanupRootStyle(svg: SVG): CleanupRootStyleResult;
export { cleanupRootStyle };