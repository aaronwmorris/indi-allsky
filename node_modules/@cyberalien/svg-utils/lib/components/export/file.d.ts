import { FactoryIconData } from "../types/data.js";
import { ComponentFactoryFileSystemOptions } from "../types/options.js";
import { FactoryComponent, FactoryGeneratedComponent } from "../types/component.js";
interface Options extends Pick<ComponentFactoryFileSystemOptions, 'doubleDirsForComponents' | 'prefixDirsForComponents'> {
  includePrefix?: boolean | string;
  extension: string;
  cssExtension?: string;
}
/**
 * Add icon and filename to generated component
 */
declare function convertGeneratedComponentToFile(icon: Pick<FactoryIconData, 'name' | 'prefix'>, item: FactoryGeneratedComponent, options: Options): FactoryComponent;
export { convertGeneratedComponentToFile };