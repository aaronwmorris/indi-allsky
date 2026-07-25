import { ComponentFactoryOptions, GeneratedAssetPath } from "../../types/options.js";
/**
 * Generate CSS filename based on options
 */
declare function getGeneratedCSSFilename(name: string, options: Pick<ComponentFactoryOptions, 'cssPath' | 'doubleDirsForCSS'>): GeneratedAssetPath;
export { getGeneratedCSSFilename };