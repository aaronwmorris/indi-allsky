/**
* Add component dependencies to set
*/
function addComponentDependencies(component, dependencies) {
	if (component.dependencies) for (const dependency of component.dependencies) dependencies.add(dependency);
}
/**
* Create dependencies list for package.json
*/
function createDependenciesForPackage(dependencies, customVersions) {
	if (dependencies.size) {
		const result = Object.create(null);
		for (const dependency of dependencies) result[dependency] = customVersions?.[dependency] ?? "latest";
		return result;
	}
}
export { addComponentDependencies, createDependenciesForPackage };
