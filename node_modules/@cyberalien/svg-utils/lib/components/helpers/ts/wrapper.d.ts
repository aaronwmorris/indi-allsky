import { FactoryIconData } from "../../types/data.js";
import { ComponentFactoryOptions } from "../../types/options.js";
import { GeneratedAssetFile } from "../../types/component.js";
import { FactoryComponentProps } from "../props/types.js";
/**
 * Properties to omit
 */
declare const omitComponentSVGProps = "'viewBox' | 'width' | 'height' | 'xmlns'";
/**
 * Add component types
 */
declare function addComponentTypes(template: string, data: FactoryIconData, options: ComponentFactoryOptions, assets: GeneratedAssetFile[], props: FactoryComponentProps): string;
export { addComponentTypes, omitComponentSVGProps };