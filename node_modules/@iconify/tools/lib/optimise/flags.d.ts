import { SVG } from "../svg/index.js";
/**
 * De-optimise paths. Compressed paths are still not supported by some software.
 */
declare function deOptimisePaths(svg: SVG): void;
export { deOptimisePaths };