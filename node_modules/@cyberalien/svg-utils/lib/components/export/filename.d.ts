import { FactoryIconData } from "../types/data.js";
import { ComponentFactoryFileSystemOptions } from "../types/options.js";
/**
 * Generate component filename based on options
 *
 * @param icon Icon data (name and prefix)
 * @param componentExtension Component file extension (e.g. '.tsx')
 * @param options Factory options
 * @returns Generated filename
 */
declare function getGeneratedComponentFilename(icon: Pick<FactoryIconData, 'name' | 'prefix'>, componentExtension: string, options: Pick<ComponentFactoryFileSystemOptions, 'doubleDirsForComponents' | 'prefixDirsForComponents'>): string;
export { getGeneratedComponentFilename };