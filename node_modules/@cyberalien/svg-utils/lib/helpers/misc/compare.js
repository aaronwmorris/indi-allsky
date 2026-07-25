import { sortObject } from "./sort-object.js";
/**
* Compare sets, returns true if identical
*/
function compareSets(set1, set2) {
	if (!set1 || !set2) return false;
	if (set1.size !== set2.size) return false;
	for (const value of set1) if (!set2.has(value)) return false;
	return true;
}
/**
* Compare two values, returns true if identical
*/
function compareValues(value1, value2) {
	return value1 === value2 || JSON.stringify(sortObject(value1)) === JSON.stringify(sortObject(value2));
}
export { compareSets, compareValues };
