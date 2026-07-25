import { ComponentFactoryFileSystemOptions, GeneratedAssetPath } from "../../types/options.js";
/**
 * Get relative path to root directory from component
 *
 * @param options Factory options
 * @returns Asset path
 */
declare function getFactoryRelativeRootPath(options: Pick<ComponentFactoryFileSystemOptions, 'doubleDirsForComponents' | 'prefixDirsForComponents'>, pathPrefix?: string): GeneratedAssetPath;
export { getFactoryRelativeRootPath };