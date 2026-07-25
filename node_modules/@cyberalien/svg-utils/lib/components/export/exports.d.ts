import { FactoryComponent } from "../types/component.js";
type Types = string | Record<string, string>;
interface Options {
  ext?: string;
  data?: Record<string, Types>;
  defaultProp?: string;
}
/**
 * Add exports for main files to object
 */
declare function createExportsForMainFiles(data: FactoryComponent[], options?: Options): Record<string, Types>;
export { createExportsForMainFiles };