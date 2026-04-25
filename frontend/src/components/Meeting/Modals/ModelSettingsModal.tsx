// components/Meeting/Modals/ModelSettingsModal.tsx
'use client';

import { ModelConfig } from '@/types';

interface ModelSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  config: ModelConfig;
  onConfigChange: (config: ModelConfig) => void;
  models: Array<{ name: string; id: string; size: string; modified: string }>;
  error?: string;
}

export const ModelSettingsModal: React.FC<ModelSettingsModalProps> = ({
  isOpen,
  onClose,
  config,
  onConfigChange,
  models,
  error
}) => {
  if (!isOpen) return null;

  const modelOptions = {
    ollama: models.map(model => model.name),
    claude: ['claude-3-5-sonnet-latest'],
    groq: ['llama-3.3-70b-versatile'],
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold text-gray-900">Cài đặt Model</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Model tóm tắt</label>
            <div className="flex space-x-2">
              <select
                className="px-3 py-2 text-sm bg-white border border-gray-300 rounded-md"
                value={config.provider}
                onChange={(e) => {
                  const provider = e.target.value as ModelConfig['provider'];
                  onConfigChange({ ...config, provider, model: modelOptions[provider][0] });
                }}
              >
                <option value="claude">Claude</option>
                <option value="groq">Groq</option>
                <option value="ollama">Ollama</option>
              </select>
              <select
                className="flex-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md"
                value={config.model}
                onChange={(e) => onConfigChange({ ...config, model: e.target.value })}
              >
                {modelOptions[config.provider].map(model => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
          </div>
          
          {config.provider === 'ollama' && (
            <div>
              <h4 className="text-lg font-bold mb-4">Model Ollama có sẵn</h4>
              {error && <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">{error}</div>}
              <div className="grid gap-4 max-h-[400px] overflow-y-auto pr-2">
                {models.map((model) => (
                  <div 
                    key={model.id}
                    className={`bg-white p-4 rounded-lg shadow cursor-pointer transition-colors ${config.model === model.name ? 'ring-2 ring-blue-500 bg-blue-50' : 'hover:bg-gray-50'}`}
                    onClick={() => onConfigChange({ ...config, model: model.name })}
                  >
                    <h3 className="font-bold">{model.name}</h3>
                    <p className="text-gray-600">Dung lượng: {model.size}</p>
                    <p className="text-gray-600">Cập nhật: {model.modified}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        
        <div className="mt-6 flex justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700">
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
};