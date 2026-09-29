#property strict
#property service
#property version "2.00"
#property description "Relogio independente do calendario; somente leitura, sem ordens."

string Escape(string value)
  {
   StringReplace(value,"\\","\\\\");
   StringReplace(value,"\"","\\\"");
   StringReplace(value,"\r","\\r");
   StringReplace(value,"\n","\\n");
   StringReplace(value,"\t","\\t");
   return value;
  }

bool PublishClock(long sequence)
  {
   datetime utc=TimeGMT();
   datetime server=TimeTradeServer();
   if(utc<=0 || server<=0) return false;
   string json="{\"schema\":2,\"version\":\"2.00\",\"provider\":\"ScalperLabClockService\"";
   json+=",\"terminal_data_path\":\""+Escape(TerminalInfoString(TERMINAL_DATA_PATH))+"\"";
   json+=",\"account_login\":"+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   json+=",\"account_server\":\""+Escape(AccountInfoString(ACCOUNT_SERVER))+"\"";
   json+=",\"connected\":"+(TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false");
   json+=",\"captured_at_epoch\":"+IntegerToString((long)utc);
   json+=",\"trade_server_time\":\""+TimeToString(server,TIME_DATE|TIME_SECONDS)+"\"";
   json+=",\"server_utc_offset_seconds\":"+IntegerToString((long)(server-utc));
   json+=",\"sequence\":"+IntegerToString(sequence)+"}";
   int handle=FileOpen("ScalperLab_clock_v2.tmp",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(handle==INVALID_HANDLE) return false;
   uint written=FileWriteString(handle,json);
   FileFlush(handle); FileClose(handle);
   if(written==0) return false;
   return FileMove("ScalperLab_clock_v2.tmp",0,"ScalperLab_clock_v2.json",FILE_REWRITE);
  }

void OnStart()
  {
   PrintFormat("ScalperLab Clock: tipo=%s; publicacao independente a cada 10 segundos.",EnumToString((ENUM_PROGRAM_TYPE)MQLInfoInteger(MQL_PROGRAM_TYPE)));
   // Exclusive lifetime lock prevents two publishers in the same terminal.
   int lock=FileOpen("ScalperLab_clock_v2.lock",FILE_WRITE|FILE_BIN);
   if(lock==INVALID_HANDLE) { Print("ScalperLab Clock: outra instancia ativa ou arquivo sem permissao."); return; }
   long sequence=0;
   while(!IsStopped())
     {
      if(!PublishClock(++sequence)) PrintFormat("ScalperLab Clock: falha de publicacao (%d).",GetLastError());
      for(int i=0;i<10 && !IsStopped();i++) Sleep(1000);
     }
   FileClose(lock);
  }
