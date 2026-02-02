
import React from 'react';
import { Zap, Facebook, Instagram, Linkedin } from 'lucide-react';

export const Footer: React.FC = () => {
  const handleLoginClick = (e: React.MouseEvent) => {
    e.preventDefault();
    window.open('https://nitroleads.online', '_blank');
  };

  return (
    <footer className="bg-white border-t border-gray-100">
      <div className="bg-[#F8F9FA]/50 py-16">
        <div className="container mx-auto px-4 md:px-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-12 lg:gap-20">
            {/* Column 1 */}
            <div className="col-span-1 md:col-span-2">
              <div className="flex items-center gap-3 mb-8">
                <div className="bg-gradient-to-br from-[#47C1FF] to-[#0055FF] p-2 rounded-[10px] shadow-lg shadow-blue-500/20 border border-white/10">
                  <Zap className="w-5 h-5 text-white fill-white" />
                </div>
                <span className="text-2xl font-[900] tracking-tighter text-[#212529]">
                  NitroLeads
                </span>
              </div>
              <p className="text-gray-500 text-lg max-w-sm mb-8 leading-relaxed font-medium">
                Inteligência comercial estratégica para acelerar vendas B2B, focada em conectar você com quem realmente toma as decisões.
              </p>
              <div className="flex gap-5">
                {[Facebook, Instagram, Linkedin].map((Icon, i) => (
                  <a key={i} href="#" className="w-10 h-10 rounded-xl bg-white border border-gray-200 flex items-center justify-center text-gray-400 hover:text-[#0D6EFD] hover:border-[#0D6EFD] transition-all">
                    <Icon className="w-5 h-5" />
                  </a>
                ))}
              </div>
            </div>

            {/* Column 2 */}
            <div>
              <h4 className="font-black text-[#212529] mb-8 uppercase tracking-widest text-sm italic">Plataforma</h4>
              <ul className="space-y-4 text-gray-500 font-bold">
                <li><a href="#como-funciona" className="hover:text-[#0D6EFD] transition-colors">Como Funciona</a></li>
                <li><a href="#recursos" className="hover:text-[#0D6EFD] transition-colors">Recursos</a></li>
                <li><a href="https://nitroleads.online" target="_blank" rel="noopener noreferrer" className="hover:text-[#0D6EFD] transition-colors">Preços</a></li>
                <li>
                  <button 
                    onClick={handleLoginClick}
                    className="hover:text-[#0D6EFD] transition-colors text-left"
                  >
                    Login
                  </button>
                </li>
              </ul>
            </div>
          </div>

          <div className="mt-20 pt-10 border-t border-gray-200 flex flex-col md:flex-row justify-between items-center gap-6 text-xs text-gray-400 font-black uppercase tracking-[0.2em] italic">
            <p>© 2024 NitroLeads. Todos os direitos reservados.</p>
            <div className="flex items-center gap-2">
              <span>Feito para decisores</span>
              <div className="bg-gradient-to-br from-[#47C1FF] to-[#0055FF] p-1 rounded-sm">
                <Zap className="w-3 h-3 fill-white text-white" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
};
