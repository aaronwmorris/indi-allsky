/**
* Create new hash context, used to make sure all hashes within the same context are unique
*/
function createUniqueHashContext() {
	return { cache: Object.create(null) };
}
export { createUniqueHashContext };
