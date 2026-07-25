import { FactoryIconData } from "../../types/data.js";
import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentProps } from "../props/types.js";
/**
 * Add Vue component types
 */
declare const addVueComponentTypes: (data: FactoryIconData, options: ComponentFactoryOptions, assets: GeneratedAssetFile[], props: FactoryComponentProps) => string;
export { addVueComponentTypes };