import { FactoryGeneratedComponent } from "../types/component.js";
/**
 * Add component dependencies to set
 */
declare function addComponentDependencies(component: FactoryGeneratedComponent, dependencies: Set<string>): void;
/**
 * Create dependencies list for package.json
 */
declare function createDependenciesForPackage(dependencies: Set<string>, customVersions?: Record<string, string>): Record<string, string> | undefined;
export { addComponentDependencies, createDependenciesForPackage };