import { FactoryComponentImports } from "./types.js";
/**
 * Add named import
 */
declare function addNamedImport(data: FactoryComponentImports, source: string, names: string | string[]): void;
/**
 * Add type import
 */
declare function addTypeImport(data: FactoryComponentImports, source: string, types: string | string[]): void;
export { addNamedImport, addTypeImport };