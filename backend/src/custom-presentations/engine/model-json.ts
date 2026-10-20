/** Recover transport formatting only. Never evaluate model code or guess
 * missing text, numbers, array items or closing quotes. Schema validation is
 * still mandatory after every recovery. */
export function parseModelJson(text:unknown):unknown {
  if(typeof text!=='string'||!text.trim())throw new SyntaxError('Empty JSON response');
  if(text.length>1_000_000)throw new SyntaxError('JSON response exceeds size limit');
  const normalized=text.trim().replace(/^\uFEFF/,'').replace(/^```(?:json)?\s*/iu,'').replace(/\s*```$/u,'');
  try{return JSON.parse(normalized);}catch{}
  const start=normalized.search(/[\[{]/u);
  if(start<0)throw new SyntaxError('JSON object or array is missing');
  const source=normalized.slice(start),stack:string[]=[];
  let result='',quoted=false,escaped=false;
  for(let i=0;i<source.length;i++){
    const char=source[i]!;
    if(quoted){
      if(escaped){result+=char;escaped=false;continue;}
      if(char==='\\'){result+=char;escaped=true;continue;}
      if(char==='"')quoted=false;
      // Raw controls inside model strings have an unambiguous JSON escape.
      result+=char.charCodeAt(0)<32?JSON.stringify(char).slice(1,-1):char;
      continue;
    }
    if(char==='"'){quoted=true;result+=char;continue;}
    if(char==='{'||char==='['){stack.push(char==='{'?'}':']');if(stack.length>100)throw new SyntaxError('JSON nesting exceeds limit');}
    if(char==='}'||char===']'){
      if(stack.pop()!==char)throw new SyntaxError('Mismatched JSON brackets');
      result+=char;
      if(!stack.length)return JSON.parse(result);
      continue;
    }
    if(char===','&&/^\s*[\]}]/u.test(source.slice(i+1)))continue;
    result+=char;
  }
  // A truncated sentence, key, number or array member must go back to the
  // model. Do not invent the missing content or accept a partial presentation.
  throw new SyntaxError('Incomplete JSON response');
}
