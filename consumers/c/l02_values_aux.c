#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <unistd.h>
#include "reading_demo.h"
#include "reading_demo_native.h"
#ifndef MADB_LAB_AUX
#error missing auxiliary author selection
#endif
static unsigned checks;
#define CHECK(e) do{++checks;if(!(e)){fprintf(stderr,"L02 values assertion:%d:%s\n",__LINE__,#e);exit(2);}}while(0)
static int zero(const reading_demo_Reading *v){
    if(v->value || v->label.byte_count)return 0;
    for(unsigned i=0;i<64;++i)if(v->label.bytes[i])return 0;
    return 1;
}
static void quoted(const char *p){putchar('"');for(;*p;++p){if(*p=='"'||*p=='\\')putchar('\\');if((unsigned char)*p<32)printf("\\u%04x",(unsigned char)*p);else putchar(*p);}putchar('"');}
int main(int argc,char **argv){
    CHECK(argc==4);uint8_t actual[64],expected[64];CHECK(strlen(argv[3])==128);
    for(unsigned i=0;i<64;++i){unsigned v;char pair[3]={argv[3][i*2],argv[3][i*2+1],0};CHECK(sscanf(pair,"%2x",&v)==1);expected[i]=(uint8_t)v;}
    CHECK(reading_demo_bootstrap_v1(1,actual,64)==0 && memcmp(actual,expected,64)==0);
    Dl_info image;CHECK(dladdr((void *)(uintptr_t)reading_demo_bootstrap_v1,&image)!=0 && image.dli_fname);
    printf("{\"event\":\"binding\",\"image\":");quoted(image.dli_fname);printf(",\"identity\":\"");for(unsigned i=0;i<64;++i)printf("%02x",actual[i]);printf("\",\"pid\":%ld}\n",(long)getpid());
    reading_demo_Reading input={0};input.value=7;input.label.byte_count=3;memcpy(input.label.bytes,"abc",3);
    reading_demo_Reading before=input;
#if MADB_LAB_AUX == 1
    CHECK(strcmp(argv[1],"output-capacity")==0);
    reading_demo_ReadingResult r=reading_demo_grow(input);CHECK(r.kind==4 && r.status==9);
#elif MADB_LAB_AUX == 2
    CHECK(strcmp(argv[1],"unwind")==0);
    reading_demo_ReadingResult r=reading_demo_explode(input);CHECK(r.kind==4 && r.status==8);
#else
#error unknown auxiliary author
#endif
    CHECK(r.error.domain==0 && r.error.code==0 && zero(&r.value));CHECK(memcmp(&input,&before,sizeof input)==0);
    printf("{\"result\":\"passed\",\"mode\":\"%s\",\"author\":%d,\"checks\":%u,\"helper_vectors\":0,\"scope\":\"native-sdk\"}\n",argv[1],MADB_LAB_AUX+4,checks);return 0;
}
