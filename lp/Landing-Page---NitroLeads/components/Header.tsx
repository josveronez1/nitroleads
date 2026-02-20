
import React, { useState, useEffect } from 'react';
import { Zap, Menu, X, ArrowRight } from 'lucide-react';
import { trackMetaLead } from '../lib/utils';

interface HeaderProps {
  isBannerVisible?: boolean;
}

export const Header: React.FC<HeaderProps> = ({ isBannerVisible = false }) => {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const navLinks = [
    { name: 'Como Funciona', href: '#como-funciona' },
    { name: 'Recursos', href: '#recursos' },
    { name: 'FAQ', href: '#faq' },
  ];

  const handleLoginClick = (e: React.MouseEvent) => {
    e.preventDefault();
    trackMetaLead('CTA_HEADER_LOGIN');
    window.open('https://nitroleads.online', '_blank');
  };

  const scrollToSection = (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    e.preventDefault();
    const targetId = href.replace('#', '');
    const element = document.getElementById(targetId);
    
    if (element) {
      const headerOffset = isBannerVisible ? 120 : 80;
      const elementPosition = element.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

      window.scrollTo({
        top: offsetPosition,
        behavior: 'smooth'
      });
    }
    setIsMobileMenuOpen(false);
  };

  const topClass = isBannerVisible ? 'top-10' : 'top-0';

  return (
    <header className={`fixed ${topClass} left-0 right-0 z-50 transition-all duration-500 ${isScrolled ? 'bg-white/90 backdrop-blur-xl shadow-xl py-3 border-b border-gray-100' : 'bg-transparent py-6'}`}>
      <div className="container mx-auto px-4 md:px-6 flex items-center justify-between">
        <a href="/" className="flex items-center gap-3 group cursor-pointer">
          <div className="bg-gradient-to-br from-[#47C1FF] to-[#0055FF] p-2 rounded-[12px] group-hover:rotate-12 transition-transform duration-300 shadow-lg shadow-blue-500/40 border border-white/20">
            <Zap className="w-5 h-5 text-white fill-white" />
          </div>
          <span className="text-2xl font-[900] tracking-tighter text-[#212529]">
            Nitro<span className="text-[#0D6EFD]">Leads</span>
          </span>
        </a>

        {/* Desktop Nav */}
        <nav className="hidden md:flex items-center gap-2 bg-gray-100/40 p-1.5 rounded-2xl border border-gray-200/50 backdrop-blur-sm">
          {navLinks.map((link) => (
            <a 
              key={link.name} 
              href={link.href}
              onClick={(e) => scrollToSection(e, link.href)}
              className="nav-link-premium text-sm font-bold text-[#212529]/70 hover:text-[#0D6EFD] px-4 py-2 rounded-xl transition-all"
            >
              {link.name}
            </a>
          ))}
        </nav>

        <div className="hidden md:flex items-center gap-6">
          <button 
            onClick={handleLoginClick}
            className="text-sm font-black text-gray-500 hover:text-[#0D6EFD] transition-colors uppercase tracking-widest"
          >
            Login
          </button>
          <a 
            href="#cta" 
            onClick={(e) => {
              trackMetaLead('CTA_HEADER_ACESSAR_PLATAFORMA');
              scrollToSection(e, '#cta');
            }}
            className="nitro-gradient hover:scale-105 active:scale-95 text-white px-8 py-3.5 rounded-xl font-black text-xs shadow-2xl shadow-blue-500/30 flex items-center gap-2 transition-all glow-button uppercase tracking-tighter italic"
          >
            Acessar Plataforma <ArrowRight className="w-4 h-4" />
          </a>
        </div>

        {/* Mobile Toggle */}
        <button 
          className="md:hidden p-2 rounded-xl bg-gray-100 text-[#212529]"
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
        >
          {isMobileMenuOpen ? <X /> : <Menu />}
        </button>
      </div>

      {/* Mobile Menu */}
      {isMobileMenuOpen && (
        <div className="md:hidden absolute top-full left-4 right-4 mt-3 bg-white rounded-3xl shadow-2xl border border-gray-100 p-8 flex flex-col gap-6 animate-in fade-in zoom-in duration-300">
          {navLinks.map((link) => (
            <a 
              key={link.name} 
              href={link.href}
              onClick={(e) => scrollToSection(e, link.href)}
              className="text-xl font-[900] text-[#212529] py-4 border-b border-gray-50 flex justify-between items-center group uppercase italic tracking-tighter"
            >
              {link.name}
              <ArrowRight className="w-6 h-6 opacity-40 group-hover:opacity-100 transition-all text-[#0D6EFD]" />
            </a>
          ))}
          <div className="flex flex-col gap-4 mt-2">
            <a 
              href="#cta" 
              onClick={(e) => {
                trackMetaLead('CTA_HEADER_COMECAR_AGORA');
                scrollToSection(e, '#cta');
              }}
              className="nitro-gradient text-white w-full py-6 rounded-2xl font-[900] shadow-2xl text-center uppercase tracking-widest italic text-lg"
            >
              Começar Agora
            </a>
            <button 
              onClick={handleLoginClick}
              className="text-center py-4 font-black text-gray-400 uppercase text-sm tracking-widest"
            >
              Já tenho uma conta
            </button>
          </div>
        </div>
      )}
    </header>
  );
};
