import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentImports } from "../imports/types.js";
/**
 * Adds replaceIDs() function to assets
 */
declare function addReplaceIDsFunctionAsset(imports: FactoryComponentImports, assets: GeneratedAssetFile[], options: Pick<ComponentFactoryOptions, 'rootPath' | 'helpersDirectory'>): string;
export { addReplaceIDsFunctionAsset };