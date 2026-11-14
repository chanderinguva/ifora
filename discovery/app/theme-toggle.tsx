'use client';

import {Moon,Sun} from 'lucide-react';
import {useTheme} from 'next-themes';
import {useSyncExternalStore} from 'react';

const subscribe=()=>()=>{};

export default function ThemeToggle(){
  const {resolvedTheme,setTheme}=useTheme();
  const mounted=useSyncExternalStore(subscribe,()=>true,()=>false);
  const dark=mounted&&resolvedTheme==='dark';
  return <button className="themeToggle" type="button" aria-label={dark?'Use light theme':'Use dark theme'} title={dark?'Use light theme':'Use dark theme'} onClick={()=>setTheme(dark?'light':'dark')}>
    {dark?<Sun size={16}/>:<Moon size={16}/>}<span>{dark?'Light':'Dark'}</span>
  </button>;
}
