import { FactoryIconData } from "../../types/data.js";
import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentProps } from "../props/types.js";
/**
 * Add Svelte component types
 */
declare const addSvelteComponentTypes: (data: FactoryIconData, options: ComponentFactoryOptions, assets: GeneratedAssetFile[], props: FactoryComponentProps) => string;
export { addSvelteComponentTypes };