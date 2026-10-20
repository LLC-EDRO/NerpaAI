/** A numbered source row has a structural ordinal and one semantic heading.
 * Some authors bind the heading to both. Convert only that redundant ordinal
 * marker; never drop or rewrite the actual heading or explanation. */
export function normalizeHtmlNumbers(html:string|undefined){
 if(!html)return html;
 // Some JSON responses escape HTML attribute quotes twice. This changes code
 // quoting only; audience text lives in separate validated content fields.
 html=html.replace(/\\(["'])/g,'$1');
 const counts=new Map<string,number>();
 for(const match of html.matchAll(/\bdata-text\s*=\s*["']((?:steps|cards)\.(\d+)\.title)["']/g))counts.set(match[1]!,1+(counts.get(match[1]!)??0));
 for(const [path,count] of counts){
   if(count!==2)continue;
   const escaped=path.replaceAll('.','\\.');
   const marker=new RegExp(`<(?:strong|span)\\b[^>]*\\bdata-text\\s*=\\s*["']${escaped}["'][^>]*>\\s*</(?:strong|span)>`);
   const match:RegExpMatchArray|null=html.match(marker);if(!match)continue;
   html=html.replace(match[0],match[0].replace(/data-text\s*=\s*["'][^"']+["']/,`data-number="${Number(path.split('.')[1])+1}"`));
 }
 return html;
}
