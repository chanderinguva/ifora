import type {Metadata} from 'next';
import ThemeProvider from './theme-provider';
import './globals.css';

export const metadata:Metadata={
  title:'Ifora Discovery',
  description:'From a rough idea to work worth shipping',
  icons:{icon:'/favicon.svg',shortcut:'/favicon.svg',apple:'/favicon.svg'},
};

export default function Layout({children}:{children:React.ReactNode}){
  return <html lang="en" suppressHydrationWarning><body><ThemeProvider>{children}</ThemeProvider></body></html>;
}
