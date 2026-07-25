import { UniqueHashPartialOptions } from "../../../helpers/hash/types.js";
import { FactoryIconData } from "../../types/data.js";
import { ComponentFactoryFileSystemOptions, GeneratedAssetPath } from "../../types/options.js";
interface Options extends Pick<UniqueHashPartialOptions, 'context'>, Pick<ComponentFactoryFileSystemOptions, 'rootPath' | 'doubleDirsForComponents' | 'prefixDirsForComponents' | 'sharedTypes'> {}
/**
 * Generate component types filename based on options
 */
declare function getGeneratedComponentTypesFilename(icon: Pick<FactoryIconData, 'name' | 'prefix'>, content: string, options: Options): GeneratedAssetPath;
export { getGeneratedComponentTypesFilename };