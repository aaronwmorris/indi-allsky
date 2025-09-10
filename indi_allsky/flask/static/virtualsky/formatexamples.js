
// Update anchor now that we've updated the page		
if(location.hash) document.location = location.hash;

var d = new Date(document.lastModified);
str = d.toUTCString().replace(/[^\,]+\, /,"").replace(/ [0-9]{2}\:[0-9]{2}\:[0-9]{2} [^\s]+/,"").replace(/^0/,"");
S('.lastupdated').html(str);
S('.lastupdatedyear').html(d.getUTCFullYear());


// Format examples nicely to show how they were done
var examples = S('.example-code');
function tidy(t){ return t.replace(/===NEWLINE===/g,"\n").replace(/\n*$/,"").replace(/^\n*/,""); }
function sanitise(t){ return t.replace(/\</g,"&lt;").replace(/\>/g,"&gt;"); }
function deindent(t){ var indent = ""; t.replace(/^([\s\t]+)/,function(m,p1,p2){ indent = m; }); return t.replace(new RegExp(indent,'g'),"").replace(/[\s\t]+$/,""); }

function highlight(el){
	var els = S(examples[el]).find('.prettyprint');
	for(var i = 0; i < els.length; i++){

		// Add styling to code blocks
		hljs.highlightBlock(els[i]);

		// Get the final markup
		markup = S(els[i]).html()

		// Make JSON files into links
		markup = markup.replace(/([\"\'])([^\"\']*\.json)([\"\'])/g,function(m,p1,p2,p3){ return p1+'<a href="'+p2+'">'+p2+'</a>'+p3; });

		// Add back to the document
		S(els[i]).html(markup);
	}

}

for(var i = 0; i < examples.length; i++){
	html = examples[i].innerHTML;
	css = "";
	js = "";
	json = "";
	temp = html.replace(/\n/g,"===NEWLINE===").replace(/<!-- HTML -->/i,"");
	temp = temp.replace(/<!-- Javascript -->/i,"").replace(/<script>(.*)<\/script>/,function(m,p1){
		js = js+tidy(p1);
		return "";
	})
	
	temp = temp.replace(/<!-- CSS -->/i,"").replace(/<style>(.*)<\/style>/,function(m,p1){
		css = tidy(p1);
		return "";
	});

	code = sanitise(tidy(temp));
	code = code.replace(/(src|href)=\"([^\"]+)\"/g,function(m,p1,p2){ return p1+'="<a href="'+p2+'">'+p2+'</a>"'; });
	
	showtitle = true;
	if(S(examples[i]).attr('data-title')=="false") showtitle = false;

	code = deindent(code);

	// Append the 'How to do it' content
	S(examples[i]).prepend((showtitle ? '<h3>How to do it</h3>':'')+(css ? (showtitle ? '<h4>CSS</h4>':'')+'<pre class="prettyprint lang-css">'+deindent(sanitise(css))+'</pre>':'')+(js ? (showtitle ? '<h4>Javascript</h4>':'')+'<pre class="prettyprint lang-js">'+deindent(sanitise(js))+'</pre>':'')+(code && showtitle ? '<h4>HTML</h4>':'')+(code ? '<pre class="prettyprint lang-html">'+deindent(code)+'</pre>':'')+'<h3>Result</h3>')

	highlight(i);
}
