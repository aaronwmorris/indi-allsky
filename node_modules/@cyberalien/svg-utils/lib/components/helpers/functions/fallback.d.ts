import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentImports } from "../imports/types.js";
/**
 * Adds getFallback() function to assets
 */
declare function addFallbackFunctionAsset(imports: FactoryComponentImports, assets: GeneratedAssetFile[], options: Pick<ComponentFactoryOptions, 'rootPath' | 'helpersDirectory'>, defaultValues: Record<string, boolean | string>): string;
export { addFallbackFunctionAsset };