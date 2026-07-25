import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentImports } from "../imports/types.js";
interface Data {
  functionName: string;
  content: string;
  exportNames?: Set<string>;
  jsName?: string;
}
/**
 * Adds a custom function to assets
 */
declare function addCustomFunctionAsset(imports: FactoryComponentImports, assets: GeneratedAssetFile[], options: Pick<ComponentFactoryOptions, 'rootPath' | 'helpersDirectory'>, data: Data): void;
export { addCustomFunctionAsset };