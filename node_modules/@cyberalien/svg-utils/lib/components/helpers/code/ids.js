const regex = /\sid="/g;
/**
* Check if content has IDs to replace
*/
function checkForUniqueIDs(content) {
	return !!regex.exec(content);
}
export { checkForUniqueIDs };
